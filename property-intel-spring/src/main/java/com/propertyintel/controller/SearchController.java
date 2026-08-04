package com.propertyintel.controller;


import com.propertyintel.dto.request.SearchRequest;
import com.propertyintel.dto.response.ListingCardResponse;
import com.propertyintel.service.ListingService;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Page;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api")
@RequiredArgsConstructor
public class SearchController {
    private final ListingService listingService;

    @PostMapping("/search")
    public ResponseEntity<Page<ListingCardResponse>> searchListings(@RequestBody SearchRequest request) {
        Page<ListingCardResponse> result = listingService.searchListings(request);
        return ResponseEntity.ok(result);
    }

}
