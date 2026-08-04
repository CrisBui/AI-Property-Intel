package com.propertyintel.dto.response;

import lombok.AccessLevel;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;
import lombok.experimental.FieldDefaults;

import java.time.LocalDateTime;

@Data
@NoArgsConstructor
@AllArgsConstructor
@FieldDefaults(level = AccessLevel.PRIVATE)
public class ListingCardResponse {
    String sourceId;
    String title;
    Long priceVnd;
    Float areaM2;
    String district;
    String addressText;
    String contactPhone;
    LocalDateTime postedAt;
    String shortDescription;
    String longDescription;
}
