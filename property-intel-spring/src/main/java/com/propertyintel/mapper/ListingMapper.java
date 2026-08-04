package com.propertyintel.mapper;


import com.propertyintel.dto.response.ListingCardResponse;
import com.propertyintel.dto.response.ListingDetailResponse;
import com.propertyintel.entity.Listing;
import org.mapstruct.Mapper;

@Mapper(componentModel = "Spring")
public interface ListingMapper {
    ListingCardResponse toCardResponse(Listing listing);

    ListingDetailResponse toDetailResponse(Listing listing);
}
